"""Tests for llm-kit. No network: every provider response is a fake.

That constraint is the point. A test suite that calls a real LLM is slow, costs money,
burns free-tier quota, and - worst - is non-deterministic, so a red build tells you
nothing about whether you broke something. The *plumbing* (retries, budgets, validation,
the tool loop's message ordering) is fully deterministic and belongs in pytest. Judging
whether the model's answer is any good is a different activity with a different name -
evals - and it lives in a project's `evals/`, not here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel, Field

from llm_kit import (
    LLM,
    Ledger,
    LLMBudgetError,
    LLMOutputError,
    LLMPermanentError,
    LLMTransientError,
    RetryPolicy,
    Settings,
    Tool,
    ToolError,
    Usage,
    classify,
    cost_usd,
    dispatch,
    price_for,
    with_retries,
)

# --------------------------------------------------------------------- fake responses


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunction
    type: str = "function"


@dataclass
class FakeMessage:
    content: str | None = None
    tool_calls: list[FakeToolCall] | None = None


@dataclass
class FakeChoice:
    message: FakeMessage
    finish_reason: str = "stop"


@dataclass
class FakeUsage:
    prompt_tokens: int = 100
    completion_tokens: int = 50
    completion_tokens_details: Any = None


@dataclass
class FakeResponse:
    choices: list[FakeChoice]
    usage: FakeUsage | None = None


def text_response(text: str, *, finish_reason: str = "stop", **usage: int) -> FakeResponse:
    return FakeResponse([FakeChoice(FakeMessage(content=text), finish_reason)], FakeUsage(**usage))


def tool_response(name: str, arguments: str, call_id: str = "call_1") -> FakeResponse:
    return FakeResponse(
        [
            FakeChoice(
                FakeMessage(
                    content=None, tool_calls=[FakeToolCall(call_id, FakeFunction(name, arguments))]
                ),
                "tool_calls",
            )
        ],
        FakeUsage(),
    )


class ScriptedClient:
    """Stands in for `client.chat.completions`. Hands back queued responses in order."""

    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("the client was called more times than the test scripted")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def make_llm(responses: list[Any], **kwargs: Any) -> tuple[LLM, ScriptedClient]:
    """An LLM wired to a scripted client. `min_interval_s=0` so tests do not sleep."""
    llm = LLM(
        provider="groq",
        settings=Settings(groq_api_key="test-key"),
        min_interval_s=0.0,
        **kwargs,
    )
    scripted = ScriptedClient(responses)
    llm.client.chat.completions = scripted  # type: ignore[assignment]
    return llm, scripted


def api_error(status: int, retry_after: str | None = None) -> openai.APIStatusError:
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(
        status, headers=headers, request=httpx.Request("POST", "https://example.test")
    )
    return openai.APIStatusError("boom", response=response, body=None)


# --------------------------------------------------------------------- pricing


def test_cost_is_computed_from_the_published_per_million_rates():
    # 1M in + 1M out on gpt-oss-20b at $0.075 / $0.30.
    assert cost_usd("openai/gpt-oss-20b", 1_000_000, 1_000_000) == pytest.approx(0.375)


def test_local_models_cost_nothing_in_dollars():
    assert cost_usd("qwen3.5:4b", 999_999, 999_999) == 0.0


def test_an_unknown_model_is_priced_pessimistically_and_flagged():
    """A missing price must never read as $0.00 - that is a reassuring lie in a report."""
    price, known = price_for("some-model-we-never-added")
    assert known is False
    assert price.input_per_m > 0
    assert cost_usd("some-model-we-never-added", 1_000, 1_000) > 0


# --------------------------------------------------------------------- usage / ledger


def test_usage_adds_and_reports_hidden_reasoning_tokens():
    total = Usage(10, 20, 5) + Usage(1, 2, 3)
    assert (total.prompt_tokens, total.completion_tokens, total.reasoning_tokens) == (11, 22, 8)
    assert total.total_tokens == 33


def test_usage_survives_a_provider_that_reports_nothing():
    """Ollama and some proxies omit usage entirely. That must not crash a paid call."""
    assert Usage.from_response(FakeResponse([], usage=None)) == Usage()


def test_the_cost_ceiling_blocks_the_next_call_rather_than_reporting_it_afterwards():
    ledger = Ledger(max_usd=0.0000001)
    llm, _ = make_llm([text_response("one"), text_response("two")], ledger=ledger)
    llm.complete("first call goes through")
    with pytest.raises(LLMBudgetError, match="cost budget exhausted"):
        llm.complete("second call must not be sent")


def test_the_call_ceiling_blocks_runaway_loops():
    ledger = Ledger(max_calls=1)
    llm, _ = make_llm([text_response("one")], ledger=ledger)
    llm.complete("ok")
    with pytest.raises(LLMBudgetError, match="call budget"):
        llm.complete("blocked")


def test_a_failed_call_is_still_recorded():
    """A ledger that only shows successes understates what a run actually did."""
    ledger = Ledger()
    llm, _ = make_llm([api_error(401)], ledger=ledger)
    with pytest.raises(LLMPermanentError):
        llm.complete("this fails")
    assert len(ledger.records) == 1
    assert ledger.records[0].error is not None


# --------------------------------------------------------------------- retry


@pytest.mark.parametrize("status", [429, 500, 503, 504])
def test_server_side_and_rate_limit_errors_are_transient(status):
    assert isinstance(classify(api_error(status)), LLMTransientError)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_side_errors_are_permanent_and_must_not_be_retried(status):
    assert isinstance(classify(api_error(status)), LLMPermanentError)


def test_transport_failures_with_no_status_code_are_transient():
    assert isinstance(classify(httpx.ConnectError("dns")), LLMTransientError)


def test_retry_after_is_honoured_when_the_provider_sends_one():
    error = classify(api_error(429, retry_after="7"))
    assert isinstance(error, LLMTransientError)
    assert error.retry_after == 7.0
    assert RetryPolicy().delay_for(1, error.retry_after) == 7.0


def test_retry_after_is_capped_so_one_bad_header_cannot_hang_a_worker():
    assert RetryPolicy(max_delay_s=30).delay_for(1, retry_after=3600) == 30


def test_backoff_is_jittered_within_the_exponential_bound():
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=100.0)
    # Attempt 3 => bound of 1 * 2**2 = 4. Full jitter samples [0, 4].
    delays = [policy.delay_for(3) for _ in range(50)]
    assert all(0 <= d <= 4 for d in delays)
    assert len(set(delays)) > 1, "no jitter means a synchronised retry wave"


def test_a_transient_failure_is_retried_and_then_succeeds():
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise api_error(503)
        return "ok"

    result, used = with_retries(flaky, RetryPolicy(max_attempts=4, base_delay_s=0.0))
    assert result == "ok"
    assert used == 3


def test_a_permanent_failure_is_raised_on_the_first_attempt():
    attempts = {"n": 0}

    def bad_key() -> str:
        attempts["n"] += 1
        raise api_error(401)

    with pytest.raises(LLMPermanentError):
        with_retries(bad_key, RetryPolicy(max_attempts=4, base_delay_s=0.0))
    assert attempts["n"] == 1, "retrying a 401 makes one clear error into a slow one"


# --------------------------------------------------------------------- completions


def test_complete_returns_text_and_records_the_call():
    ledger = Ledger()
    llm, _ = make_llm(
        [text_response("hello", prompt_tokens=12, completion_tokens=3)], ledger=ledger
    )
    result = llm.complete("hi")
    assert result.text == "hello"
    assert ledger.records[0].usage.prompt_tokens == 12
    assert ledger.total_usd > 0


def test_truncation_is_detectable_rather_than_silent():
    llm, _ = make_llm([text_response("half an ans", finish_reason="length")])
    assert llm.complete("write an essay").truncated is True


def test_a_system_message_is_placed_first():
    llm, scripted = make_llm([text_response("ok")])
    llm.complete("user text", system="you are terse")
    sent = scripted.calls[0]["messages"]
    assert sent[0] == {"role": "system", "content": "you are terse"}
    assert sent[1]["role"] == "user"


# --------------------------------------------------------------------- structured output


class Invoice(BaseModel):
    vendor: str
    total: float = Field(gt=0)
    currency: str


def test_structured_output_returns_a_validated_model():
    payload = json.dumps({"vendor": "Acme", "total": 42.5, "currency": "USD"})
    llm, _ = make_llm([text_response(payload)])
    invoice = llm.complete_structured("extract it", Invoice)
    assert invoice.vendor == "Acme"
    assert invoice.total == 42.5


def test_invalid_output_is_repaired_on_a_second_attempt():
    """Layer 3: hand the model its own broken output plus the validator's complaint."""
    bad = json.dumps({"vendor": "Acme", "total": -5, "currency": "USD"})  # gt=0 fails
    good = json.dumps({"vendor": "Acme", "total": 5, "currency": "USD"})
    llm, scripted = make_llm([text_response(bad), text_response(good)])
    invoice = llm.complete_structured("extract it", Invoice, repair_attempts=1)
    assert invoice.total == 5
    repair_messages = scripted.calls[1]["messages"]
    assert repair_messages[-1]["role"] == "user"
    assert "did not validate" in repair_messages[-1]["content"]


def test_repair_attempts_are_capped_so_a_bad_schema_cannot_bill_forever():
    bad = json.dumps({"vendor": "Acme", "total": -5, "currency": "USD"})
    ledger = Ledger()
    llm, _ = make_llm([text_response(bad), text_response(bad)], ledger=ledger)
    with pytest.raises(LLMOutputError) as exc:
        llm.complete_structured("extract it", Invoice, repair_attempts=1)
    assert exc.value.raw is not None, "the raw text is what you need to debug this"
    assert len(ledger.records) == 2


def test_truncated_json_is_reported_as_truncation_not_as_a_bad_prompt():
    """The symptom is 'invalid JSON'; the cause is max_tokens. Say so."""
    llm, _ = make_llm([text_response('{"vendor": "Ac', finish_reason="length")])
    with pytest.raises(LLMOutputError, match="max_tokens"):
        llm.complete_structured("extract it", Invoice, repair_attempts=0)


# --------------------------------------------------------------------- tools


class WeatherArgs(BaseModel):
    city: str = Field(min_length=1, max_length=60)


def _weather(args: WeatherArgs) -> str:
    if args.city.lower() != "karachi":
        raise ToolError(f"no data for {args.city!r}; this tool only knows Karachi")
    return json.dumps({"city": "Karachi", "temp_c": 31})


WEATHER_TOOL = Tool(
    name="get_weather",
    description="Look up the current weather for one city.",
    args_model=WeatherArgs,
    func=_weather,
)


def test_the_schema_is_generated_from_the_pydantic_model():
    schema = WEATHER_TOOL.schema()
    assert schema["function"]["name"] == "get_weather"
    assert "city" in schema["function"]["parameters"]["properties"]
    assert schema["function"]["parameters"]["additionalProperties"] is False


def test_a_hallucinated_tool_name_cannot_execute():
    outcome = dispatch({"get_weather": WEATHER_TOOL}, "c1", "rm_rf", "{}")
    assert outcome.ok is False
    assert "unknown_tool" in outcome.content
    assert "get_weather" in outcome.content, "tell the model what it could have called"


def test_malformed_json_arguments_become_a_tool_result_not_an_exception():
    outcome = dispatch({"get_weather": WEATHER_TOOL}, "c1", "get_weather", '{"city": ')
    assert outcome.ok is False
    assert "invalid_json_arguments" in outcome.content


def test_arguments_are_validated_before_the_function_runs():
    """Lab 04 caught TypeError; Pydantic catches 'city was 40,000 characters long'."""
    outcome = dispatch(
        {"get_weather": WEATHER_TOOL}, "c1", "get_weather", json.dumps({"city": "x" * 500})
    )
    assert outcome.ok is False
    assert "invalid_arguments" in outcome.content


def test_a_tool_that_says_no_returns_an_actionable_message():
    outcome = dispatch(
        {"get_weather": WEATHER_TOOL}, "c1", "get_weather", json.dumps({"city": "Oslo"})
    )
    assert outcome.ok is False
    assert "only knows Karachi" in outcome.content


def test_a_crashing_tool_is_reported_as_our_bug_not_the_models():
    def explode(args: WeatherArgs) -> str:
        raise RuntimeError("index out of range")

    broken = Tool("boom", "d", WeatherArgs, explode)
    outcome = dispatch({"boom": broken}, "c1", "boom", json.dumps({"city": "Karachi"}))
    assert outcome.ok is False
    assert "tool_crashed" in outcome.content
    assert "Do not retry" in outcome.content


# --------------------------------------------------------------------- agent loop


def test_the_loop_runs_a_tool_and_then_returns_the_final_answer():
    llm, scripted = make_llm(
        [
            tool_response("get_weather", json.dumps({"city": "Karachi"})),
            text_response("It is 31C in Karachi."),
        ]
    )
    result = llm.call_tools("weather in Karachi?", [WEATHER_TOOL])
    assert result.completed
    assert result.iterations == 2
    assert result.text == "It is 31C in Karachi."
    assert len(result.outcomes) == 1 and result.outcomes[0].ok


def test_the_assistant_message_precedes_its_tool_results():
    """Swap this order and the provider returns a 400. It is protocol, not style."""
    llm, _ = make_llm(
        [
            tool_response("get_weather", json.dumps({"city": "Karachi"})),
            text_response("done"),
        ]
    )
    result = llm.call_tools("weather?", [WEATHER_TOOL])
    roles = [m["role"] for m in result.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert result.messages[2]["tool_call_id"] == result.messages[1]["tool_calls"][0]["id"]


def test_every_tool_call_id_gets_exactly_one_tool_message():
    llm, _ = make_llm(
        [
            FakeResponse(
                [
                    FakeChoice(
                        FakeMessage(
                            tool_calls=[
                                FakeToolCall(
                                    "a", FakeFunction("get_weather", '{"city":"Karachi"}')
                                ),
                                FakeToolCall("b", FakeFunction("get_weather", '{"city":"Oslo"}')),
                            ]
                        ),
                        "tool_calls",
                    )
                ],
                FakeUsage(),
            ),
            text_response("done"),
        ]
    )
    result = llm.call_tools("two cities", [WEATHER_TOOL])
    tool_ids = [m["tool_call_id"] for m in result.messages if m["role"] == "tool"]
    assert tool_ids == ["a", "b"], "a missing tool message is a 400 on the next request"


def test_the_iteration_cap_stops_a_model_stuck_in_a_tool_loop():
    forever = [tool_response("get_weather", json.dumps({"city": "Oslo"})) for _ in range(10)]
    llm, _ = make_llm(forever)
    result = llm.call_tools("loop", [WEATHER_TOOL], max_iterations=3)
    assert result.stop_reason == "max_iterations"
    assert result.iterations == 3


def test_the_budget_stops_the_loop_even_below_the_iteration_cap():
    ledger = Ledger(max_calls=2)
    forever = [tool_response("get_weather", json.dumps({"city": "Oslo"})) for _ in range(10)]
    llm, _ = make_llm(forever, ledger=ledger)
    result = llm.call_tools("loop", [WEATHER_TOOL], max_iterations=10)
    assert result.stop_reason == "budget"
    assert len(ledger.records) == 2


def test_a_tool_call_truncated_by_max_tokens_is_named_as_such():
    truncated = FakeResponse(
        [
            FakeChoice(
                FakeMessage(tool_calls=[FakeToolCall("a", FakeFunction("get_weather", '{"ci'))]),
                "length",
            )
        ],
        FakeUsage(),
    )
    llm, _ = make_llm([truncated])
    result = llm.call_tools("weather?", [WEATHER_TOOL])
    assert result.stop_reason == "truncated_tool_call"
