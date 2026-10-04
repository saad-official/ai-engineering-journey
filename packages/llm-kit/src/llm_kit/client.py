"""The client. Four methods, one provider-agnostic surface.

    complete()              text in, text out
    complete_structured()   text in, a validated Pydantic instance out
    stream()                text in, tokens out as they arrive
    call_tools()            text in, an agent loop, a final answer out

Everything else in this package exists to serve these four. If a fifth method is ever
tempting, it probably belongs in the project, not in here - this is a provider layer, not
a framework. The line: llm-kit knows about *providers*, projects know about *problems*.

Every call routes through `_execute`, which is the single place that knows how to check a
budget, time a request, retry it, record what it cost, and translate a vendor exception.
One chokepoint is the entire reason cost accounting is reliable: there is nowhere else a
call can be made from.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from .errors import LLMBudgetError, LLMOutputError
from .providers import DEFAULT_PROVIDER, Provider, Settings, resolve
from .retry import RetryPolicy, with_retries
from .schema import require_all_properties, to_provider_schema
from .tools import Tool, ToolOutcome, dispatch
from .usage import CallRecord, Ledger, Usage

TModel = TypeVar("TModel", bound=BaseModel)

Messages = str | Sequence[dict[str, Any]]


@dataclass
class Completion:
    """One finished call: the text, and everything needed to explain the text."""

    text: str
    record: CallRecord
    finish_reason: str | None = None
    raw: Any = None

    @property
    def truncated(self) -> bool:
        """`length` means the model was cut off mid-thought.

        Checked explicitly everywhere in this library because truncation is the failure
        that does not look like one: you get a plausible answer that simply stops, and
        with structured output you get JSON missing its closing brace. Lab 03 voided an
        entire 45-call run to this.
        """
        return self.finish_reason == "length"


@dataclass
class AgentResult:
    """The outcome of a `call_tools` loop: the answer, the transcript, and the receipts."""

    text: str
    messages: list[dict[str, Any]]
    outcomes: list[ToolOutcome] = field(default_factory=list)
    iterations: int = 0
    stop_reason: str = "final_answer"  # or: max_iterations, deadline, budget

    @property
    def completed(self) -> bool:
        return self.stop_reason == "final_answer"


def _as_messages(messages: Messages, system: str | None) -> list[dict[str, Any]]:
    """Accept a bare string or a full message array; always return an array.

    The convenience matters less than the invariant: everything below this line works on
    one shape, so there is exactly one place where a message array is built.
    """
    if isinstance(messages, str):
        built: list[dict[str, Any]] = [{"role": "user", "content": messages}]
    else:
        built = [dict(message) for message in messages]
    if system is not None:
        built.insert(0, {"role": "system", "content": system})
    return built


class LLM:
    """A configured connection to one provider and one model.

    Construct one per role, not one per call:

        classifier = LLM(provider="groq", tier="fast",    ledger=ledger, label="classify")
        writer     = LLM(provider="gemini", tier="quality", ledger=ledger, label="prose")

    That is model routing, and it is a two-line pattern rather than a framework feature.
    Sharing one `Ledger` between them is what makes a per-run cost report possible.
    """

    def __init__(
        self,
        *,
        provider: str = DEFAULT_PROVIDER,
        model: str | None = None,
        tier: str = "fast",
        settings: Settings | None = None,
        ledger: Ledger | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout_s: float = 60.0,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        label: str = "",
        min_interval_s: float | None = None,
    ):
        self.provider: Provider
        self.provider, api_key = resolve(provider, settings)
        self.model = model or (
            self.provider.quality_model if tier == "quality" else self.provider.fast_model
        )
        self.ledger = ledger if ledger is not None else Ledger()
        self.retry_policy = retry_policy or RetryPolicy()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.label = label or self.model

        # Client-side pacing. Free tiers rate-limit by requests per minute, and the
        # cheapest way to not get 429s is to not send them: sleeping 2s is strictly
        # better than sending, being rejected, and backing off 2s anyway.
        if min_interval_s is not None:
            self.min_interval_s = min_interval_s
        elif self.provider.free_rpm:
            self.min_interval_s = 60.0 / self.provider.free_rpm
        else:
            self.min_interval_s = 2.0  # conservative default where RPM is UNVERIFIED
        self._last_call_at = 0.0

        self.client = OpenAI(api_key=api_key, base_url=self.provider.base_url, timeout=timeout_s)

    # ------------------------------------------------------------------ internals

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_call_at
        if self._last_call_at and elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_call_at = time.monotonic()

    def _execute(self, label: str, call: Callable[[], Any]) -> tuple[Any, CallRecord]:
        """The single chokepoint: budget -> pace -> time -> retry -> record."""
        blocked = self.ledger.would_exceed()
        if blocked is not None:
            raise LLMBudgetError(blocked)

        self._pace()
        started = time.monotonic()
        try:
            raw, attempts = with_retries(call, self.retry_policy)
        except Exception as exc:
            # A failed call still consumed wall-clock time and possibly provider quota, so
            # it is recorded. A ledger that only shows successes understates what a run
            # actually did, which is the opposite of the point.
            self.ledger.add(
                CallRecord(
                    provider=self.provider.name,
                    model=self.model,
                    label=label,
                    usage=Usage(),
                    latency_s=time.monotonic() - started,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise

        choice = raw.choices[0] if getattr(raw, "choices", None) else None
        record = self.ledger.add(
            CallRecord(
                provider=self.provider.name,
                model=self.model,
                label=label,
                usage=Usage.from_response(raw),
                latency_s=time.monotonic() - started,
                finish_reason=getattr(choice, "finish_reason", None),
                attempts=attempts,
            )
        )
        return raw, record

    def _params(self, **overrides: Any) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        params.update({k: v for k, v in overrides.items() if v is not None})
        return params

    # ------------------------------------------------------------------ public API

    def complete(
        self,
        messages: Messages,
        *,
        system: str | None = None,
        label: str | None = None,
        **overrides: Any,
    ) -> Completion:
        """Text in, text out."""
        payload = _as_messages(messages, system)
        raw, record = self._execute(
            label or self.label,
            lambda: self.client.chat.completions.create(
                messages=payload, **self._params(**overrides)
            ),
        )
        choice = raw.choices[0]
        return Completion(
            text=choice.message.content or "",
            record=record,
            finish_reason=choice.finish_reason,
            raw=raw,
        )

    def complete_structured(
        self,
        messages: Messages,
        schema: type[TModel],
        *,
        system: str | None = None,
        label: str | None = None,
        repair_attempts: int = 1,
        **overrides: Any,
    ) -> TModel:
        """Text in, a *validated* instance of `schema` out.

        Three layers, each catching what the previous one cannot:

          1. Ask the provider to constrain generation to the schema (`json_schema`). Where
             supported this is grammar-level enforcement - the model physically cannot emit
             a token that breaks the shape. Where it is not, we fall back to `json_object`,
             which promises valid JSON and nothing about its shape.
          2. Validate with Pydantic anyway. Always. Native structured output still fails on
             semantics (an enum value that does not exist, a date in the wrong format), and
             on some providers `json_schema` is advisory rather than enforced. Never trust
             a model's output because a vendor said the mode was strict.
          3. If validation fails, hand the model its own broken output plus the validator's
             complaint and ask for a correction. This is the expensive path and it is
             capped: `repair_attempts=1` by default, because a model that got the shape
             wrong twice will usually get it wrong a third time, and each attempt is a
             full-price call.
        """
        payload = _as_messages(messages, system)
        # NOT `schema.model_json_schema()`. Pydantic's raw output is valid JSON Schema and
        # is rejected by every strict structured-output implementation we use - the first
        # live run of smoke.py died on exactly this. See schema.py for why.
        json_schema = to_provider_schema(schema)

        if self.provider.structured_mode == "json_schema":
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": require_all_properties(json_schema),
                    "strict": True,
                },
            }
        else:
            response_format = {"type": "json_object"}
            # With no schema enforcement, the schema has to travel in the prompt instead.
            payload.append(
                {
                    "role": "system",
                    "content": (
                        "Reply with a single JSON object and nothing else. It must "
                        f"validate against this JSON Schema:\n{json.dumps(json_schema)}"
                    ),
                }
            )

        attempt = 0
        last_error = ""
        last_text = ""
        while True:
            raw, _ = self._execute(
                label or f"{self.label}:structured",
                # `messages=payload` is bound as a default argument rather than captured
                # from the enclosing scope: `payload` is rebound at the bottom of this
                # loop to add the repair turn, and a late-binding closure would send the
                # repaired conversation on the attempt that was meant to be the first one.
                lambda messages=payload: self.client.chat.completions.create(
                    messages=messages,
                    response_format=response_format,
                    **self._params(**overrides),
                ),
            )
            choice = raw.choices[0]
            last_text = choice.message.content or ""

            if choice.finish_reason == "length":
                # Diagnosed separately because the symptom - "invalid JSON" - points at
                # the prompt when the actual cause is max_tokens. Hours have been lost here.
                last_error = (
                    "the response was cut off by max_tokens (finish_reason='length'), so "
                    f"the JSON is incomplete. Raise max_tokens above {self.max_tokens}."
                )
            else:
                try:
                    return schema.model_validate_json(last_text)
                except ValidationError as exc:
                    last_error = str(exc)
                except ValueError as exc:  # not JSON at all
                    last_error = f"response was not valid JSON: {exc}"

            if attempt >= repair_attempts:
                raise LLMOutputError(
                    f"could not get a valid {schema.__name__} after {attempt + 1} "
                    f"attempt(s). Last error: {last_error}",
                    raw=last_text,
                )

            attempt += 1
            payload = [
                *payload,
                {"role": "assistant", "content": last_text},
                {
                    "role": "user",
                    "content": (
                        "That response did not validate. Fix it and reply with the "
                        f"corrected JSON object only.\n\nValidation error:\n{last_error}"
                    ),
                },
            ]

    def stream(
        self,
        messages: Messages,
        *,
        system: str | None = None,
        label: str | None = None,
        **overrides: Any,
    ) -> Iterator[str]:
        """Yield text chunks as they arrive.

        Streaming is a latency illusion and a good one: total time to the last token is
        unchanged (often slightly worse), but time to the *first* token drops from seconds
        to milliseconds, and a user reading along does not experience the wait.

        The catch worth knowing: a streamed response cannot be validated before the user
        starts reading it. Anything that must be checked - a schema, a moderation pass, a
        citation verification - cannot be streamed straight to a UI. This is why
        `complete_structured` does not stream.
        """
        blocked = self.ledger.would_exceed()
        if blocked is not None:
            raise LLMBudgetError(blocked)

        payload = _as_messages(messages, system)
        self._pace()
        started = time.monotonic()
        usage = Usage()
        finish_reason: str | None = None

        # `stream_options={"include_usage": True}` is what makes a streamed call auditable:
        # without it the provider sends no usage block at all and the cost of every
        # streamed call silently becomes zero in the ledger.
        stream = self.client.chat.completions.create(
            messages=payload,
            stream=True,
            stream_options={"include_usage": True},
            **self._params(**overrides),
        )
        try:
            for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = Usage.from_response(chunk)
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                content = getattr(choice.delta, "content", None)
                if content:
                    yield content
        finally:
            # In a `finally` because a consumer that breaks out of the loop early still
            # spent the tokens the provider already generated.
            self.ledger.add(
                CallRecord(
                    provider=self.provider.name,
                    model=self.model,
                    label=label or f"{self.label}:stream",
                    usage=usage,
                    latency_s=time.monotonic() - started,
                    finish_reason=finish_reason,
                )
            )

    def call_tools(
        self,
        messages: Messages,
        tools: Sequence[Tool],
        *,
        system: str | None = None,
        label: str | None = None,
        max_iterations: int = 6,
        deadline_s: float = 120.0,
        on_step: Callable[[int, Any, list[ToolOutcome]], None] | None = None,
        **overrides: Any,
    ) -> AgentResult:
        """The agent loop: model -> tool calls -> execute -> results -> repeat -> answer.

        This is lab 04's loop, hardened. Two guards rather than one, and the second answers
        the open question lab 04 ended on:

          max_iterations   caps the number of *steps*. Stops a model that keeps retrying a
                           tool that keeps failing.
          deadline_s       caps total *wall-clock* time. A tool that hangs for 90 seconds
                           six times over passes the iteration cap comfortably while
                           taking nine minutes. Step count and elapsed time are different
                           failures and need different limits.

        A budget on the shared Ledger is the third guard and applies automatically, since
        every call inside the loop goes through `_execute`.
        """
        registry = {tool.name: tool for tool in tools}
        schemas = [tool.schema() for tool in tools]
        payload = _as_messages(messages, system)
        outcomes: list[ToolOutcome] = []
        started = time.monotonic()

        for iteration in range(1, max_iterations + 1):
            if time.monotonic() - started > deadline_s:
                return AgentResult("", payload, outcomes, iteration - 1, "deadline")

            try:
                raw, _ = self._execute(
                    label or f"{self.label}:agent",
                    lambda: self.client.chat.completions.create(
                        messages=payload,
                        tools=schemas,
                        **self._params(**overrides),
                    ),
                )
            except LLMBudgetError:
                return AgentResult("", payload, outcomes, iteration - 1, "budget")

            choice = raw.choices[0]
            message = choice.message
            tool_calls = getattr(message, "tool_calls", None) or []

            # The assistant message is appended BEFORE the tool results, always. The
            # protocol requires a `tool` message to follow the assistant message that
            # requested it; swap the order and the next request is a 400.
            payload.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    **(
                        {
                            "tool_calls": [
                                {
                                    "id": call.id,
                                    "type": "function",
                                    "function": {
                                        "name": call.function.name,
                                        "arguments": call.function.arguments,
                                    },
                                }
                                for call in tool_calls
                            ]
                        }
                        if tool_calls
                        else {}
                    ),
                }
            )

            if not tool_calls:
                result = AgentResult(
                    message.content or "", payload, outcomes, iteration, "final_answer"
                )
                if on_step is not None:
                    on_step(iteration, message, [])
                return result

            if choice.finish_reason == "length":
                # Truncation during a tool call is worse than truncation in prose: the
                # `arguments` string is cut mid-JSON, so the call is unrunnable and the
                # model has no idea. Caught here so the loop reports the real cause.
                return AgentResult("", payload, outcomes, iteration, "truncated_tool_call")

            step_outcomes: list[ToolOutcome] = []
            for call in tool_calls:
                outcome = dispatch(registry, call.id, call.function.name, call.function.arguments)
                step_outcomes.append(outcome)
                outcomes.append(outcome)
                payload.append(
                    {"role": "tool", "tool_call_id": outcome.call_id, "content": outcome.content}
                )

            if on_step is not None:
                on_step(iteration, message, step_outcomes)

        return AgentResult("", payload, outcomes, max_iterations, "max_iterations")
