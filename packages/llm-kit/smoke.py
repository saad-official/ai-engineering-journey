"""A live smoke test: all four methods against a real provider, ~6 calls, a cost report.

The pytest suite proves the plumbing is correct against fakes. This proves the fakes
resemble reality - that the provider really does accept our schema, really does return the
usage block we parse, and really does emit tool calls in the shape the loop expects. Both
are needed; neither replaces the other.

    uv run smoke.py                 # Groq (fast, 30 RPM free)
    uv run smoke.py --provider gemini
"""

from __future__ import annotations

import argparse
import sys

from pydantic import BaseModel, Field

from llm_kit import LLM, Ledger, Tool, ToolError

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class Repo(BaseModel):
    """Small on purpose: this is a plumbing check, not an extraction benchmark."""

    name: str = Field(description="The repository name only, without the owner.")
    language: str = Field(description="The primary programming language.")
    stars: int = Field(ge=0, description="Star count as an integer.")


class SearchArgs(BaseModel):
    package: str = Field(min_length=1, max_length=80)


def _lookup_version(args: SearchArgs) -> str:
    """A fixture, deliberately offline: this lab checks the loop, not a registry."""
    versions = {"expo": "54.0.2", "react-native": "0.83.1", "zod": "4.1.0"}
    key = args.package.strip().lower()
    if key not in versions:
        raise ToolError(
            f"no version data for {args.package!r}. This tool only covers: "
            f"{', '.join(sorted(versions))}."
        )
    return f'{{"package":"{key}","latest":"{versions[key]}"}}'


VERSION_TOOL = Tool(
    name="lookup_latest_version",
    description=(
        "Return the latest published version of one npm package. Covers only a small "
        "fixed set of packages; anything else returns an error naming the ones it knows."
    ),
    args_model=SearchArgs,
    func=_lookup_version,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="groq")
    args = parser.parse_args()

    # A hard ceiling on a script that makes real calls. On free tiers this will never
    # trigger; the habit is the point, and the one time it does trigger it will be the
    # run where a loop went wrong.
    ledger = Ledger(max_usd=0.05, max_calls=12)
    llm = LLM(provider=args.provider, tier="fast", ledger=ledger, max_tokens=2048)

    print(f"provider={llm.provider.name}  model={llm.model}  pace={llm.min_interval_s:.1f}s\n")
    for quirk in llm.provider.quirks:
        print(f"  quirk: {quirk}")
    print()

    print("1) complete()")
    answer = llm.complete("Name the capital of Japan. Answer in one word.")
    print(f"   -> {answer.text.strip()!r}  truncated={answer.truncated}\n")

    print("2) complete_structured()")
    repo = llm.complete_structured(
        "The repo 'facebook/react-native' is written mainly in C++ and has about "
        "123000 stars. Extract it.",
        Repo,
    )
    print(f"   -> {repo!r}\n")

    print("3) stream()")
    print("   -> ", end="", flush=True)
    for chunk in llm.stream("Count from 1 to 5, separated by spaces. Nothing else."):
        print(chunk, end="", flush=True)
    print("\n")

    print("4) call_tools()")
    result = llm.call_tools(
        "What is the latest version of expo? Use the tool, then answer in one sentence.",
        [VERSION_TOOL],
        system="You are terse. Use the provided tools rather than guessing versions.",
        max_iterations=4,
        deadline_s=90,
    )
    print(f"   stop_reason={result.stop_reason}  iterations={result.iterations}")
    for outcome in result.outcomes:
        print(f"   tool {outcome.name}: {outcome.detail}")
    print(f"   -> {result.text.strip()!r}\n")

    print("5) failure path: a tool the model will be asked to misuse")
    bad = llm.call_tools(
        "What is the latest version of lodash? Use the tool. If it fails, say so plainly.",
        [VERSION_TOOL],
        max_iterations=4,
    )
    for outcome in bad.outcomes:
        print(f"   tool {outcome.name}: ok={outcome.ok} {outcome.detail}")
    print(f"   -> {bad.text.strip()!r}\n")

    print("-" * 78)
    print("LEDGER:", ledger.summary())
    path = ledger.write_jsonl("runs/smoke.jsonl")
    print(f"per-call records -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
