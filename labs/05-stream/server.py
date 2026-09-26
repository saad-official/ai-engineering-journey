"""Lab 05, layer 2 - the same stream, re-emitted by hand as Server-Sent Events over FastAPI.

    browser --POST /stream {"prompt"}--> this server --stream=True--> Groq / Gemini
    browser <--- text/event-stream ----- this server <--- chunks ---- provider

Why a server in the middle at all, when the browser could call Groq directly? The API key.
Anything shipped to a browser is public. The key lives in .env, is read here, and the page
never sees it - the page only ever talks to /stream. The same server is also the only place
that can enforce a prompt size limit, a rate limit, and a cost ledger, because the browser
is untrusted and can send anything.

Run:
    uv run uvicorn server:app --port 8765          # then open http://localhost:8765
    LAB05_PROVIDER=gemini uv run uvicorn server:app --port 8765

SSE event schema - one JSON object per event, `type` says which:
    {"type": "start",     "provider": str, "model": str}
    {"type": "reasoning", "text": str}              hidden thinking (Groq streams it)
    {"type": "content",   "text": str}              the visible answer
    {"type": "usage",     "prompt_tokens": int, "completion_tokens": int,
                          "reasoning_tokens": int | null}
    {"type": "done",      "finish_reason": str | null,
                          "server_ms": {"first_chunk", "first_content", "total"}, "chunks": int}
    {"type": "error",     "message": str}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from common import MAX_TOKENS, TEMPERATURE, Provider, Settings, build_provider, read_chunk

# uvicorn's own logger, so these lines appear in the same console as its access log.
log = logging.getLogger("uvicorn.error")
STATIC = Path(__file__).parent / "static"


# WHY AsyncOpenAI AND NOT THE SYNC CLIENT IN A THREADPOOL.
# An open stream spends almost all of its life WAITING - for the provider's next chunk. The
# sync client waits by blocking a thread; FastAPI would run a sync generator in its threadpool
# (anyio's default is 40 threads), so every open stream pins a thread for its whole 5-30 s,
# and stream number 41 queues behind the others. AsyncOpenAI waits with `await`: an open
# stream costs one suspended coroutine, and one thread serves them all. Two more reasons:
#   - the disconnect check below is `await request.is_disconnected()`, which a sync
#     generator cannot call without hopping back onto the event loop;
#   - a coroutine can be CANCELLED at any await. A thread blocked inside a socket read
#     cannot be interrupted from outside, so a sync stream keeps reading (and the provider
#     keeps generating) until the next chunk happens to arrive.
# This is the same reason a React Native app does network I/O off the JS thread's critical
# path: the work is waiting, and waiting should not occupy a worker.
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the client once per process, close it on shutdown (connection pool reuse)."""
    name = os.getenv("LAB05_PROVIDER", "groq")
    app.state.provider = build_provider(Settings(), name)
    app.state.client = None
    if app.state.provider is None:
        log.error("lab05: no API key for %r in .env - /stream will return an error event", name)
    else:
        p: Provider = app.state.provider
        # max_retries=0: a retry after the first chunk would replay the answer from the top
        # into a page that is already showing half of it.
        app.state.client = AsyncOpenAI(
            base_url=p.base_url, api_key=p.api_key, timeout=60.0, max_retries=0
        )
        log.info("lab05: provider=%s model=%s", p.name, p.model)
    yield
    if app.state.client is not None:
        await app.state.client.close()


app = FastAPI(title="lab05-stream", lifespan=lifespan)


class StreamRequest(BaseModel):
    # The cap is a COST control, not a UX nicety: the browser is untrusted, and without a
    # limit anyone who can reach this endpoint decides how big your input bill is.
    prompt: str = Field(min_length=1, max_length=4000)


def sse(event: dict[str, Any]) -> str:
    """Frame one event.

    SSE is a line protocol over a normal HTTP response that simply never ends:
        data: <payload>\\n        a field line; several `data:` lines are joined with \\n
        \\n                        a BLANK line ends the event - that is the dispatch signal
    Nothing else delimits events. No length prefix, no closing tag. So the blank line is the
    whole framing, and the client cannot act on an event until it has seen it (index.html's
    line buffer exists because of exactly this).

    Why JSON per event, not the raw text: the model's answer contains newlines - three
    paragraphs means "\\n\\n", which IS the event terminator. Sent raw, the first paragraph
    break would end the event mid-answer. json.dumps escapes every newline into the two
    characters `\\n`, so a payload can never contain a real one. JSON also carries the `type`,
    so reasoning, content, usage and errors share one stream and one parser.

    (SSE also has an `event:` field for named events. EventSource needs a listener per name;
    since the page parses by hand anyway, a `type` key in the JSON is one switch statement.)
    """
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def sse_events(prompt: str, request: Request) -> AsyncIterator[str]:
    """Pull chunks from the provider, push SSE events to the browser, stop if nobody listens."""
    p: Provider | None = request.app.state.provider
    client: AsyncOpenAI | None = request.app.state.client
    if p is None or client is None:
        yield sse({"type": "error", "message": "server has no API key for this provider"})
        return

    t0 = time.perf_counter()  # not monotonic(): 15.6 ms ticks on Windows/3.12, see main.py
    first_chunk: float | None = None
    first_content: float | None = None
    finish: str | None = None
    usage: dict[str, Any] | None = None
    chunks = 0
    outcome = "incomplete"
    upstream = None
    yield sse({"type": "start", "provider": p.name, "model": p.model})
    try:
        upstream = await client.chat.completions.create(
            model=p.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            stream=True,
            stream_options={"include_usage": True},  # section B of main.py is why
        )
        async for chunk in upstream:
            # CLIENT DISCONNECT. Tokens the provider generates after the user closed the tab
            # or hit Stop are still BILLED, and nobody will ever read them. The provider
            # cannot know the user left; only this server can, and only if it looks. So
            # look, once per chunk (cheap: a non-blocking peek at the ASGI receive channel),
            # and on disconnect stop reading. `finally` closes the upstream connection,
            # which is the only "stop generating" signal an HTTP API has.
            if await request.is_disconnected():
                outcome = "client disconnected (checked)"
                log.warning("lab05: client disconnected after %d chunks - closing upstream", chunks)
                return
            chunks += 1
            now = time.perf_counter() - t0
            if first_chunk is None:
                first_chunk = now
            d = read_chunk(chunk)
            if d.reasoning:
                yield sse({"type": "reasoning", "text": d.reasoning})
            if d.content:
                if first_content is None:
                    first_content = now
                yield sse({"type": "content", "text": d.content})
            if d.finish_reason:
                finish = d.finish_reason
            if d.usage:
                usage = d.usage
        if usage is not None:
            yield sse({"type": "usage", **usage})
        else:
            log.warning("lab05: stream finished with NO usage - this call is missing from cost")

        def ms(v: float | None) -> int | None:
            return None if v is None else round(v * 1000)

        yield sse(
            {
                "type": "done",
                "finish_reason": finish,
                "server_ms": {
                    "first_chunk": ms(first_chunk),
                    "first_content": ms(first_content),
                    "total": ms(time.perf_counter() - t0),
                },
                "chunks": chunks,
            }
        )
        outcome = f"complete, finish_reason={finish}"
    except (asyncio.CancelledError, GeneratorExit):
        # The OTHER disconnect path. The check above only runs when a chunk arrives; while
        # the provider is still thinking (Gemini's hidden reasoning can be seconds of
        # silence) nothing arrives. Starlette notices the disconnect itself and cancels this
        # generator (or its next write fails and it is closed). Either way we land here.
        outcome = "client disconnected (cancelled)"
        log.warning("lab05: generator cancelled after %d chunks - closing upstream", chunks)
        raise
    except Exception as e:  # noqa: BLE001 - surface provider errors to the page, don't 500
        outcome = f"error {type(e).__name__}"
        log.exception("lab05: upstream error")
        yield sse({"type": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"})
    finally:
        if upstream is not None:
            # Shielded because anyio cancellation is level-triggered: inside a cancelled
            # scope EVERY await is cancelled again, including this cleanup one. Unshielded,
            # the close would itself be cancelled and the socket left for the GC to find.
            with anyio.CancelScope(shield=True):
                await upstream.close()
        # No usage on a disconnected stream: the usage chunk comes LAST, so an early close
        # means the cost of this call is unknown. That is a real gap in any cost ledger.
        log.info(
            "lab05: %s | chunks=%d first_chunk=%s first_content=%s usage=%s",
            outcome,
            chunks,
            None if first_chunk is None else f"{first_chunk:.2f}s",
            None if first_content is None else f"{first_content:.2f}s",
            usage,
        )


@app.post("/stream")
async def stream(body: StreamRequest, request: Request) -> StreamingResponse:
    return StreamingResponse(
        sse_events(body.prompt, request),
        media_type="text/event-stream",
        headers={
            # Every hop between here and the browser that BUFFERS turns a stream back into a
            # slow non-streamed response. no-cache stops caches holding it; X-Accel-Buffering
            # stops nginx-style proxies (Render, many PaaS) collecting the body before
            # forwarding. A gzip middleware would do the same thing - do not add one here.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/")
async def index() -> FileResponse:
    # Same origin as /stream, so the page needs no CORS configuration at all.
    return FileResponse(STATIC / "index.html")


# No rate_limit() here, deliberately. common.rate_limit() is time.sleep(), which would freeze
# the event loop and every other open stream with it. One human clicking a button cannot hit
# 30 RPM; a real multi-user service needs a per-user async token bucket, not a sleep.
