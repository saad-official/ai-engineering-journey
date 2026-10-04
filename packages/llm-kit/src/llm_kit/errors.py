"""The error taxonomy. Four kinds, because each one wants a different reaction.

Collapsing LLM failures into one exception type is how you get a client that retries a
bad API key 5 times and gives up on a 429 that would have succeeded 2 seconds later.

    LLMTransientError   429, 500, 502, 503, 504, timeouts, dropped connections.
                        RETRY with backoff. The request was fine; the moment was not.
    LLMPermanentError   400, 401, 403, 404, 422. Bad key, bad model id, malformed
                        request, schema the provider rejects. RETRYING IS A BUG - the
                        same request will fail identically, just slower and 5x over.
    LLMBudgetError      our own guard fired: token budget, cost ceiling, wall-clock
                        deadline, iteration cap. NOT the provider's fault. Never retry.
    LLMOutputError      the call succeeded and the *content* is unusable: invalid JSON,
                        JSON that fails Pydantic validation, truncated mid-object.
                        Retry-able, but only with a changed prompt (see repair in
                        client.complete_structured), not with the identical request.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class, so callers can catch everything from this library with one except."""


class LLMTransientError(LLMError):
    """Provider-side and probably temporary. Safe to retry with backoff."""

    def __init__(
        self, message: str, *, status: int | None = None, retry_after: float | None = None
    ):
        super().__init__(message)
        self.status = status
        # Providers send `Retry-After` on 429. Honouring it is the difference between
        # backing off politely and being rate-limited harder for hammering.
        self.retry_after = retry_after


class LLMPermanentError(LLMError):
    """The request itself is wrong. Fix the code, do not retry."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class LLMBudgetError(LLMError):
    """One of OUR limits stopped the call. A cost control doing its job, not a failure."""


class LLMOutputError(LLMError):
    """The model answered, but the answer could not be parsed or validated."""

    def __init__(self, message: str, *, raw: str | None = None):
        super().__init__(message)
        # Keep the raw text: the single most useful thing when a schema fails in prod is
        # seeing exactly what the model actually emitted.
        self.raw = raw
