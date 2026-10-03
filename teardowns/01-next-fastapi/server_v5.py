"""Teardown 01, the port: the same backend, rewritten to speak what today's useChat expects.

The original (teardowns/_src/.../api/index.py) was written for AI SDK 4's "data stream" (lines
like `0:"text"`, `9:{tool call}`, `a:{tool result}`, `d:{finish}`). The frontend in the same
folder was later upgraded to AI SDK 5+, whose default transport speaks the "UI message stream":
SSE events, one JSON object each, `type` saying what it is. Captures F-H show the result: the
real client gets a 422 on the way in, and if it ever got the legacy bytes, it would render
nothing and raise nothing.

    browser (useChat + DefaultChatTransport)
       |  POST /api/chat  {id, messages: UIMessage[], trigger, messageId}
       v
    THIS SERVER  -- UIMessage[] -> OpenAI messages (to_openai_messages)
       |           -- step loop: stream model, collect tool calls, run tools, repeat
       |  text/event-stream, header x-vercel-ai-ui-message-stream: v1
       v
    data: {"type":"start","messageId":...}
    data: {"type":"start-step"}
    data: {"type":"tool-input-start" | "tool-input-available" | "tool-output-available", ...}
    data: {"type":"finish-step"}
    data: {"type":"start-step"}
    data: {"type":"text-start"} {"type":"text-delta"}... {"type":"text-end"}
    data: {"type":"finish-step"}
    data: {"type":"finish","finishReason":"stop","messageMetadata":{usage...}}
    data: [DONE]

Fixes over the original, each marked FIX-n below and explained in NOTES.md:
  FIX-1  accept UIMessage `parts`, not a `content` string (the 422)
  FIX-2  emit the UI message stream protocol, with its header
  FIX-3  assemble tool calls by `index`, tolerating "all args in one chunk" (Gemini) as well as
         "id first, args trickle in" (OpenAI); the original dropped Gemini's args
  FIX-4  decide "this step called tools" from the tool calls collected, not finish_reason
         (Gemini says "stop" after a tool call; the original then emitted nothing)
  FIX-5  loop: after tool results, call the model AGAIN so it can answer in words. The
         original stopped after the tool result and left the user with a JSON blob.
  FIX-6  usage: keep the LAST usage seen per step (Gemini sends a running total on every
         chunk; OpenAI sends one final choices=[] chunk), and request it explicitly
  FIX-7  never forward a None delta as text (the original printed the string "None")
  FIX-8  echo Gemini's thought_signature back with the tool call (provider state leaking
         through an "OpenAI-compatible" API)
  FIX-9  AsyncOpenAI + disconnect check + error part, from Lab 05
  FIX-10 bad tool args / tool exceptions become `tool-output-error`, fed back to the model,
         instead of a crash halfway through a 200 response

Run:  uv run uvicorn server_v5:app --port 8001
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("uvicorn.error")

WORKSPACE = Path(__file__).resolve().parents[2]
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-3.5-flash-lite"
PRICE_IN_PER_M, PRICE_OUT_PER_M = 0.30, 2.50  # USD, same table as labs 01-05
MAX_STEPS = 4  # model -> tools -> model -> ... ; a hard stop so a tool loop can't run forever
MAX_TOKENS = 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=WORKSPACE / ".env", extra="ignore")
    gemini_api_key: SecretStr


# ---------------------------------------------------------------- tools (same as the original)


def get_current_weather(location: str, unit: Literal["celsius", "fahrenheit"] = "fahrenheit"):
    # Deterministic instead of random.randint, so captures are reproducible and a test can
    # assert on the number. A fake tool should be boring.
    temperature = 31 if unit == "celsius" else 88
    return {"temperature": temperature, "unit": unit, "location": location}


TOOLS: dict[str, Callable[..., Any]] = {"get_current_weather": get_current_weather}
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Get the current weather in a given location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA",
                    },
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["location", "unit"],
            },
        },
    }
]


# ---------------------------------------------------------------- FIX-1: the request contract


class UIPart(BaseModel):
    """One element of UIMessage.parts. `type` decides which other fields exist:
    "text" -> text; "file" -> url, mediaType; "tool-<name>" -> toolCallId, state, input,
    output / errorText, callProviderMetadata; "step-start", "reasoning", "data-*" -> ignored here.
    Extra fields are allowed on purpose: the SDK adds part types between minor versions, and a
    strict model would turn every SDK upgrade into a 422 - the exact failure we are fixing."""

    model_config = ConfigDict(extra="allow")
    type: str


class UIMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    role: Literal["system", "user", "assistant"]
    parts: list[UIPart]


class ChatRequest(BaseModel):
    """What DefaultChatTransport POSTs (ai@7, http-chat-transport). `trigger` is
    "submit-message" or "regenerate-message"; we treat both as "answer the last message"."""

    model_config = ConfigDict(extra="allow")
    id: str
    messages: list[UIMessage] = Field(min_length=1, max_length=100)
    trigger: str | None = None
    messageId: str | None = None


def to_openai_messages(messages: list[UIMessage]) -> list[dict[str, Any]]:
    """UIMessage[] (what the UI renders) -> OpenAI chat messages (what the model reads).

    The interesting case is an ASSISTANT UIMessage that used a tool. In the UI it is ONE
    message with parts [tool-x (with input AND output), text]. The model API needs it as
    THREE-ish messages: assistant{tool_calls} -> tool{result} -> assistant{text}. The SDK's
    own convertToModelMessages() does this split in TypeScript; here it is by hand.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role != "assistant":
            content: list[dict[str, Any]] = []
            for p in m.parts:
                d = p.model_dump()
                if p.type == "text":
                    content.append({"type": "text", "text": d["text"]})
                elif p.type == "file" and str(d.get("mediaType", "")).startswith("image/"):
                    content.append({"type": "image_url", "image_url": {"url": d["url"]}})
            if content:
                out.append({"role": m.role, "content": content})
            continue

        # Assistant: walk parts in order, flushing a tool-call group whenever text follows it.
        pending_calls: list[dict[str, Any]] = []
        pending_results: list[dict[str, Any]] = []

        for p in m.parts:
            d = p.model_dump()
            if p.type.startswith("tool-") and d.get("state") in (
                "output-available",
                "output-error",
            ):
                call: dict[str, Any] = {
                    "id": d["toolCallId"],
                    "type": "function",
                    "function": {
                        "name": p.type[len("tool-") :],
                        "arguments": json.dumps(d.get("input", {})),
                    },
                }
                sig = ((d.get("callProviderMetadata") or {}).get("google") or {}).get(
                    "thought_signature"
                )
                if sig:  # FIX-8, multi-turn half: the signature survives a round-trip via the UI
                    call["extra_content"] = {"google": {"thought_signature": sig}}
                pending_calls.append(call)
                result = (
                    d.get("output")
                    if d["state"] == "output-available"
                    else {"error": d.get("errorText")}
                )
                pending_results.append(
                    {"role": "tool", "tool_call_id": d["toolCallId"], "content": json.dumps(result)}
                )
            elif p.type == "text":
                _flush_tool_group(out, pending_calls, pending_results)
                out.append({"role": "assistant", "content": d["text"]})
        _flush_tool_group(out, pending_calls, pending_results)
    return out


def _flush_tool_group(
    out: list[dict[str, Any]], calls: list[dict[str, Any]], results: list[dict[str, Any]]
) -> None:
    """assistant{tool_calls} must be followed immediately by its tool{} results, in order."""
    if calls:
        out.append({"role": "assistant", "content": None, "tool_calls": list(calls)})
        out.extend(results)
        calls.clear()
        results.clear()


# ---------------------------------------------------------------- FIX-2: the wire format


def sse(part: dict[str, Any]) -> str:
    """One UI message chunk = one SSE event. Same framing as Lab 05's sse(): `data: <json>`
    plus a blank line. JSON-encoding is what makes newlines inside the text safe."""
    return f"data: {json.dumps(part, ensure_ascii=False)}\n\n"


def _f(obj: Any, name: str) -> Any:
    """getattr that also reads dicts - provider extras (extra_content) arrive as raw dicts."""
    if obj is None:
        return None
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


async def ui_message_stream(req: ChatRequest, request: Request) -> AsyncIterator[str]:
    client: AsyncOpenAI = request.app.state.client
    messages = to_openai_messages(req.messages)
    total_in = total_out = 0
    finish_reason = "stop"
    t0 = time.perf_counter()

    yield sse({"type": "start", "messageId": f"msg-{uuid.uuid4().hex[:12]}"})
    try:
        for step in range(MAX_STEPS):
            yield sse({"type": "start-step"})
            text_id: str | None = None
            calls: dict[int, dict[str, Any]] = {}  # FIX-3: keyed by the delta's `index`
            step_usage = None
            step_finish: str | None = None

            stream = await client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
                max_tokens=MAX_TOKENS,
                stream=True,
                stream_options={"include_usage": True},  # FIX-6: OpenAI sends none without it
            )
            async for chunk in stream:
                if await request.is_disconnected():  # FIX-9: unread tokens are still billed
                    log.warning("teardown01: client gone at step %d - closing upstream", step)
                    await stream.close()
                    return
                if _f(chunk, "usage") is not None:
                    step_usage = chunk.usage  # FIX-6: last one wins (Gemini: running total)
                for choice in chunk.choices:
                    if choice.finish_reason:
                        step_finish = choice.finish_reason
                    delta = choice.delta
                    if delta.content:  # FIX-7: None/"" never become text
                        if text_id is None:
                            text_id = f"text-{step}"
                            yield sse({"type": "text-start", "id": text_id})
                        yield sse({"type": "text-delta", "id": text_id, "delta": delta.content})
                    for tc in delta.tool_calls or []:
                        # FIX-3. OpenAI: first delta has id+name, later ones only `index` +
                        # an argument fragment. Gemini: one delta with everything, and NO
                        # `index` at all (see captures/C). So: index if present, else
                        # "a new id means a new call", else "append to the latest call".
                        idx = (
                            tc.index
                            if tc.index is not None
                            else (len(calls) if tc.id else max(calls, default=0))
                        )
                        fn = tc.function
                        if idx not in calls:
                            calls[idx] = {
                                "id": tc.id or f"call-{uuid.uuid4().hex[:8]}",
                                "name": fn.name if fn else None,
                                "arguments": "",
                                "extra": _f(tc, "extra_content"),
                            }
                            yield sse(
                                {
                                    "type": "tool-input-start",
                                    "toolCallId": calls[idx]["id"],
                                    "toolName": calls[idx]["name"],
                                }
                            )
                        if fn and fn.arguments:
                            calls[idx]["arguments"] += fn.arguments
                            yield sse(
                                {
                                    "type": "tool-input-delta",
                                    "toolCallId": calls[idx]["id"],
                                    "inputTextDelta": fn.arguments,
                                }
                            )
            if text_id is not None:
                yield sse({"type": "text-end", "id": text_id})
            if step_usage is not None:
                total_in += step_usage.prompt_tokens or 0
                total_out += step_usage.completion_tokens or 0
            else:
                log.warning("teardown01: step %d had NO usage - cost ledger is short", step)

            # FIX-4: "did the model call tools?" is answered by the calls we collected.
            # finish_reason is provider-flavoured (Gemini: "stop" even after a tool call).
            if not calls:
                finish_reason = {"length": "length", "content_filter": "content-filter"}.get(
                    step_finish or "stop", "stop"
                )
                yield sse({"type": "finish-step"})
                break

            assistant_calls = []
            for c in calls.values():
                call_msg: dict[str, Any] = {
                    "id": c["id"],
                    "type": "function",
                    "function": {"name": c["name"], "arguments": c["arguments"]},
                }
                meta = None
                if c["extra"]:  # FIX-8: give Gemini its signature back on the next request
                    call_msg["extra_content"] = c["extra"]
                    meta = {"google": (c["extra"] or {}).get("google", {})}
                assistant_calls.append(call_msg)
                try:  # FIX-10: the model's JSON is untrusted input
                    args = json.loads(c["arguments"] or "{}")
                except json.JSONDecodeError as e:
                    args, err = None, f"invalid JSON arguments: {e}"
                if args is not None:
                    part = {
                        "type": "tool-input-available",
                        "toolCallId": c["id"],
                        "toolName": c["name"],
                        "input": args,
                    }
                    if meta:
                        part["providerMetadata"] = meta
                    yield sse(part)
                    fn = TOOLS.get(c["name"])
                    try:
                        if fn is None:
                            raise LookupError(f"unknown tool {c['name']!r}")
                        c["result"] = fn(**args)
                        yield sse(
                            {
                                "type": "tool-output-available",
                                "toolCallId": c["id"],
                                "output": c["result"],
                            }
                        )
                        continue
                    except Exception as e:  # noqa: BLE001 - becomes a tool error the model sees
                        err = f"{type(e).__name__}: {e}"
                    yield sse(
                        {"type": "tool-output-error", "toolCallId": c["id"], "errorText": err}
                    )
                else:
                    yield sse(
                        {
                            "type": "tool-input-error",
                            "toolCallId": c["id"],
                            "toolName": c["name"],
                            "input": c["arguments"],
                            "errorText": err,
                        }
                    )
                c["result"] = {"error": err}
            yield sse({"type": "finish-step"})

            # FIX-5: feed calls + results back and go round again for the worded answer.
            messages.append({"role": "assistant", "content": None, "tool_calls": assistant_calls})
            messages.extend(
                {"role": "tool", "tool_call_id": c["id"], "content": json.dumps(c["result"])}
                for c in calls.values()
            )
        else:
            finish_reason = "other"  # hit MAX_STEPS with the model still wanting tools
            log.warning("teardown01: MAX_STEPS=%d reached", MAX_STEPS)

        cost = total_in / 1e6 * PRICE_IN_PER_M + total_out / 1e6 * PRICE_OUT_PER_M
        log.info(
            "teardown01: in=%d out=%d cost=$%.6f %.0fms",
            total_in,
            total_out,
            cost,
            (time.perf_counter() - t0) * 1000,
        )
        yield sse(
            {
                "type": "finish",
                "finishReason": finish_reason,
                "messageMetadata": {
                    "usage": {"inputTokens": total_in, "outputTokens": total_out},
                    "costUsd": round(cost, 8),
                    "model": MODEL,
                },
            }
        )
    except Exception as e:  # noqa: BLE001 - FIX-9: a 200 is already sent; errors go IN the stream
        log.exception("teardown01: upstream error")
        yield sse({"type": "error", "errorText": f"{type(e).__name__}: {e}"})
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------- app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.client = AsyncOpenAI(  # FIX-9: one async client per process, not per request
        base_url=GEMINI_BASE_URL,
        api_key=Settings().gemini_api_key.get_secret_value(),
        timeout=60.0,
        max_retries=0,
    )
    yield
    await app.state.client.close()


app = FastAPI(title="teardown-01-v5", lifespan=lifespan)


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    return StreamingResponse(
        ui_message_stream(req, request),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",  # FIX-2
            "cache-control": "no-cache",
            "x-accel-buffering": "no",  # stop nginx-style proxies from buffering the stream
        },
    )
