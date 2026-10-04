"""Retry with exponential backoff and jitter, and the classification that drives it.

Two ideas do all the work here.

FIRST: classify before you retry. A 401 and a 429 are both "the call failed" and they
want opposite reactions. Retrying a 401 five times turns one clear error into a slow,
confusing one; not retrying a 429 throws away a request that would have succeeded on the
next breath. `classify()` is the whole difference.

SECOND: jitter is not a nicety. Without it, N concurrent callers that all get rate-limited
at the same moment all sleep exactly 1s, all wake at the same instant, and hammer the
provider in a synchronised wave - a thundering herd that reproduces the 429 that caused
it. Full jitter (sleep a random amount in [0, backoff]) spreads the retries out.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import openai

from .errors import LLMPermanentError, LLMTransientError

# 408 request timeout, 409 conflict, 429 too many requests, and the whole 5xx family.
TRANSIENT_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    """Defaults tuned for free tiers, where 429 is routine rather than exceptional."""

    max_attempts: int = 4
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
    # A cap on total time spent retrying one logical call. Without it, 4 attempts against
    # a provider honouring a 60s Retry-After can block a request handler for four minutes.
    deadline_s: float = 90.0

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        """Seconds to sleep before `attempt` (1-based). Honours Retry-After when given."""
        if retry_after is not None:
            # The provider told us exactly when to come back. Believe it, but cap it: a
            # pathological Retry-After of 3600 should fail fast, not hang a worker.
            return min(retry_after, self.max_delay_s)
        backoff = min(self.base_delay_s * (2 ** (attempt - 1)), self.max_delay_s)
        return random.uniform(0, backoff)  # full jitter


def classify(exc: Exception) -> Exception:
    """Map a provider/transport exception onto our two-branch taxonomy.

    Written against the `openai` SDK's exception hierarchy because that is the client
    every provider here is reached through, plus raw httpx for transport-level failures
    that never reach the SDK's own wrappers.
    """
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        if status in TRANSIENT_STATUS:
            retry_after = None
            # Retry-After is seconds or an HTTP date. Only the numeric form is handled;
            # the date form is rare from these vendors and backoff covers it anyway.
            header = getattr(getattr(exc, "response", None), "headers", {}) or {}
            raw = header.get("retry-after")
            if raw:
                try:
                    retry_after = float(raw)
                except ValueError:
                    retry_after = None
            return LLMTransientError(
                f"{status} from provider: {exc}", status=status, retry_after=retry_after
            )
        return LLMPermanentError(f"{status} from provider: {exc}", status=status)

    # No status code ever arrived: DNS failure, connection reset, read timeout. The
    # request may or may not have been processed - which is exactly why every call this
    # library makes must be safe to repeat (no side effects in a completion call).
    if isinstance(exc, openai.APITimeoutError | openai.APIConnectionError | httpx.TransportError):
        return LLMTransientError(f"transport failure: {type(exc).__name__}: {exc}")

    return exc


def with_retries[T](
    func: Callable[[], T],
    policy: RetryPolicy,
    *,
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> tuple[T, int]:
    """Run `func`, retrying transient failures. Returns (result, attempts_used).

    `on_retry` exists so the caller can log or count retries without this function
    importing a logger and deciding the project's logging policy for it.
    """
    started = time.monotonic()
    last: Exception | None = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return func(), attempt
        except Exception as exc:  # noqa: BLE001 - classified immediately below
            error = classify(exc)
            if not isinstance(error, LLMTransientError):
                raise error from exc
            last = error
            if attempt == policy.max_attempts:
                break
            delay = policy.delay_for(attempt, error.retry_after)
            if time.monotonic() - started + delay > policy.deadline_s:
                raise LLMTransientError(
                    f"retry deadline of {policy.deadline_s}s would be exceeded; "
                    f"giving up after {attempt} attempt(s). Last error: {error}"
                ) from exc
            if on_retry is not None:
                on_retry(attempt, error, delay)
            time.sleep(delay)

    raise LLMTransientError(
        f"all {policy.max_attempts} attempts failed. Last error: {last}"
    ) from last
