"""Run vercel/ai's ORIGINAL examples/next-fastapi backend, unmodified, against Gemini.

Why a harness instead of editing their file: a teardown studies what the code DOES. Every edit
we make to their source is a place where "what we observed" stops being "what they wrote".
So their api/index.py is imported as-is from teardowns/_src, and only two things are swapped
from the outside, both at the seams the original already has:

  1. `index.client` - a module-level OpenAI client. We replace it with one pointed at Gemini's
     OpenAI-compatible endpoint (same SDK, different base_url - Lab 01's whole lesson).
  2. the model name - hardcoded inside stream_text() as "gpt-6-astra". We wrap
     `chat.completions.create` and overwrite `model=` on the way through. Nothing else in the
     request is touched, so the tools, the missing stream_options, etc. are all theirs.

Run:  uv run uvicorn run_original:app --port 8000
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from openai import OpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

WORKSPACE = Path(__file__).resolve().parents[2]
EXAMPLE = WORKSPACE / "teardowns" / "_src" / "vercel-ai" / "examples" / "next-fastapi"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL = "gemini-3.5-flash-lite"  # same model as labs 01-05


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=WORKSPACE / ".env", extra="ignore")
    gemini_api_key: SecretStr


# The example's own imports are package-relative (`from .utils.prompt import ...`), so the
# example dir goes on sys.path and we import `api.index` as a package, the way uvicorn would.
sys.path.insert(0, str(EXAMPLE))
# index.py builds its OpenAI client AT IMPORT TIME, and the SDK refuses to construct without a
# key - so the app crashes on startup if the key is missing (fail-fast: arguably good). We
# replace that client two lines later, so a placeholder is enough; it is never sent anywhere.
os.environ.setdefault("OPENAI_API_KEY", "placeholder-replaced-below")
from api import index  # noqa: E402

gemini = OpenAI(
    base_url=GEMINI_BASE_URL,
    api_key=Settings().gemini_api_key.get_secret_value(),
    max_retries=0,  # Lab 05: a retry after the first chunk replays the answer from the top
)
_create = gemini.chat.completions.create


def _create_with_our_model(*args, **kwargs):
    kwargs["model"] = GEMINI_MODEL
    return _create(*args, **kwargs)


gemini.chat.completions.create = _create_with_our_model  # type: ignore[method-assign]
index.client = gemini
app = index.app
